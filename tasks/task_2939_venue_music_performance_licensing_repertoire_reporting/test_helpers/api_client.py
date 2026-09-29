"""
One typed method per endpoint of the Venue Music Licensing API (PRD §4).

Every method returns the raw ``requests.Response`` so callers can assert on the
status code as well as the envelope.  Paths are spelled exactly as the PRD's
endpoint table spells them: everything under the ``/licensing`` prefix except
the clock endpoint of PRD §2.4.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]
Params = Optional[Dict[str, Any]]


class LicensingApiClient(GenericApiClient):
    """HTTP surface of the licensing API, one method per PRD §4 table row."""

    # ─── The logical licensing clock (PRD §2.4) ───────────────────────────

    def set_clock(self, payload: Payload, headers: Headers = None) -> requests.Response:
        """``POST /_clock/set_current_utc`` — the one endpoint exempt from §2.1."""
        return self._request("POST", CLOCK_PATH, payload, headers)

    # ─── Societies (PRD §3.1) ─────────────────────────────────────────────

    def create_society(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/societies", payload, headers)

    def list_societies(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/societies", params, headers)

    def get_society(self, society_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/societies/{society_id}", None, headers
        )

    # ─── Rate schedules (PRD §3.2) ────────────────────────────────────────

    def create_rate_schedule(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/rate-schedules", payload, headers)

    def publish_rate_schedule(
        self, rate_schedule_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/rate-schedules/{rate_schedule_id}/publish",
            payload if payload is not None else {},
            headers,
        )

    def list_rate_schedules(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/rate-schedules", params, headers)

    def get_rate_schedule(
        self, rate_schedule_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/rate-schedules/{rate_schedule_id}", None, headers
        )

    # ─── Venues (PRD §3.3) ────────────────────────────────────────────────

    def create_venue(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/venues", payload, headers)

    def update_venue(
        self, venue_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{API_PREFIX}/venues/{venue_id}", payload, headers
        )

    def run_exemption_analysis(
        self, venue_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/venues/{venue_id}/exemption-analysis",
            payload if payload is not None else {},
            headers,
        )

    def list_venues(self, headers: Headers, params: Params = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/venues", params, headers)

    def get_venue(self, venue_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/venues/{venue_id}", None, headers)

    # ─── Licence applications (PRD §3.4) ──────────────────────────────────

    def create_application(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/license-applications", payload, headers
        )

    def update_application(
        self, application_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "PATCH",
            f"{API_PREFIX}/license-applications/{application_id}",
            payload,
            headers,
        )

    def submit_application(
        self, application_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/license-applications/{application_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def review_application(
        self, application_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/license-applications/{application_id}/review",
            payload,
            headers,
        )

    def withdraw_application(
        self, application_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/license-applications/{application_id}/withdraw",
            payload if payload is not None else {},
            headers,
        )

    def list_applications(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/license-applications", params, headers
        )

    def get_application(
        self, application_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/license-applications/{application_id}", None, headers
        )

    # ─── Licences (PRD §3.6, §3.7) ────────────────────────────────────────

    def activate_license(
        self, license_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/licenses/{license_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def suspend_license(
        self, license_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/licenses/{license_id}/suspend", payload, headers
        )

    def reinstate_license(
        self, license_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/licenses/{license_id}/reinstate",
            payload if payload is not None else {},
            headers,
        )

    def terminate_license(
        self, license_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/licenses/{license_id}/terminate", payload, headers
        )

    def renew_license(
        self, license_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/licenses/{license_id}/renew", payload, headers
        )

    def list_licenses(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/licenses", params, headers)

    def get_license(self, license_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/licenses/{license_id}", None, headers
        )

    # ─── Coverage windows (PRD §3.6) ──────────────────────────────────────

    def create_coverage_window(
        self, license_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/licenses/{license_id}/coverage-windows",
            payload,
            headers,
        )

    def list_license_coverage_windows(
        self, license_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/licenses/{license_id}/coverage-windows",
            params,
            headers,
        )

    def list_coverage_windows(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/coverage-windows", params, headers)

    def get_coverage_window(
        self, coverage_window_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/coverage-windows/{coverage_window_id}", None, headers
        )
    # ─── Repertoire works (PRD §3.1) ──────────────────────────────────────

    def create_repertoire_work(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/repertoire-works", payload, headers
        )

    def list_repertoire_works(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/repertoire-works", params, headers)

    def get_repertoire_work(
        self, work_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/repertoire-works/{work_id}", None, headers
        )

    # ─── Performance reports (PRD §3.8) ───────────────────────────────────

    def create_performance_report(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/performance-reports", payload, headers
        )

    def create_setlist_entry(
        self, report_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/performance-reports/{report_id}/setlist-entries",
            payload,
            headers,
        )

    def list_report_setlist_entries(
        self, report_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/performance-reports/{report_id}/setlist-entries",
            params,
            headers,
        )

    def submit_performance_report(
        self, report_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/performance-reports/{report_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def review_performance_report(
        self, report_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/performance-reports/{report_id}/review",
            payload,
            headers,
        )

    def list_performance_reports(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/performance-reports", params, headers
        )

    def get_performance_report(
        self, report_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/performance-reports/{report_id}", None, headers
        )

    # ─── Setlist entries (PRD §3.8) ───────────────────────────────────────

    def list_setlist_entries(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/setlist-entries", params, headers)

    def get_setlist_entry(
        self, setlist_entry_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/setlist-entries/{setlist_entry_id}", None, headers
        )

    # ─── Audit cases and settlement (PRD §3.9) ────────────────────────────

    def create_audit_case(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/audit-cases", payload, headers)

    def issue_findings(
        self, audit_case_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/audit-cases/{audit_case_id}/findings",
            payload if payload is not None else {},
            headers,
        )

    def close_audit_case(
        self, audit_case_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/audit-cases/{audit_case_id}/close", payload, headers
        )

    def propose_settlement(
        self, audit_case_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/audit-cases/{audit_case_id}/settlement-offer",
            payload,
            headers,
        )

    def dispute_settlement(
        self, audit_case_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/audit-cases/{audit_case_id}/dispute",
            payload if payload is not None else {},
            headers,
        )

    def settle_audit_case(
        self, audit_case_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/audit-cases/{audit_case_id}/settle",
            payload if payload is not None else {},
            headers,
        )

    def list_audit_cases(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/audit-cases", params, headers)

    def get_audit_case(
        self, audit_case_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/audit-cases/{audit_case_id}", None, headers
        )

    # ─── Fee assessments (PRD §3.9) ───────────────────────────────────────

    def pay_assessment(
        self, assessment_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/fee-assessments/{assessment_id}/pay",
            payload,
            headers,
        )

    def list_fee_assessments(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/fee-assessments", params, headers)

    def get_fee_assessment(
        self, assessment_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/fee-assessments/{assessment_id}", None, headers
        )
