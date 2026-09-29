"""HTTP client for the Neighborhood Camera Video Request & Community Safety Portal API.

One method per declared endpoint. Every method returns the raw response so a
test can assert on the status code as well as on the body, and every method
returns the envelope untouched — unwrapping is the validators' job, and doing it
in exactly one place keeps ``data`` from being read twice.

Every route is rooted at the ``/neighborhood-safety`` prefix except the logical
clock control, which sits outside the mount.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so two spellings of one instant match.

    Timestamps are rendered with three fractional digits, but an equal instant
    may legitimately arrive with none, with fewer digits or with trailing
    zeroes. Comparisons therefore run on the canonical form
    ``YYYY-MM-DDTHH:MM:SS.mmmZ`` rather than on the raw strings, so that
    ``2026-08-08T01:00:00Z`` and ``2026-08-08T01:00:00.000Z`` compare equal.
    """
    if value is None or not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[: 10 + text[10:].index("+")]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the contract declares."""

    # ── Logical clock ──────────────────────────────────────────────────────

    def set_clock(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", CLOCK_PATH, payload, headers)

    # ── Agencies ───────────────────────────────────────────────────────────

    def create_agency(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/agencies", payload, headers)

    def get_agency(self, agency_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/agencies/{agency_id}", None, headers)

    def review_agency_onboarding(
        self, agency_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/agencies/{agency_id}/onboarding-review", payload, headers
        )

    def change_agency_status(
        self, agency_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/agencies/{agency_id}/status-change", payload, headers
        )

    # ── Officers ───────────────────────────────────────────────────────────

    def create_officer(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/officers", payload, headers)

    def get_officer(self, officer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/officers/{officer_id}", None, headers)

    def list_officers(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/officers", params, headers)

    # ── Residents ──────────────────────────────────────────────────────────

    def create_resident(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/residents", payload, headers)

    def get_resident(
        self, resident_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/residents/{resident_id}", None, headers)

    def update_alert_settings(
        self, resident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{API_PREFIX}/residents/{resident_id}/alert-settings", payload, headers
        )

    def exercise_data_control(
        self, resident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/residents/{resident_id}/data-controls", payload, headers
        )

    def list_notification_dispatches(
        self, resident_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/residents/{resident_id}/notification-dispatches",
            params,
            headers,
        )

    def list_data_control_actions(
        self, resident_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/residents/{resident_id}/data-control-actions",
            params,
            headers,
        )

    # ── Devices ────────────────────────────────────────────────────────────

    def create_device(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/devices", payload, headers)

    def get_device(self, device_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/devices/{device_id}", None, headers)

    def list_devices(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/devices", params, headers)

    def update_device(
        self, device_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"{API_PREFIX}/devices/{device_id}", payload, headers)

    # ── Canvass areas ──────────────────────────────────────────────────────

    def create_request_area(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/request-areas", payload, headers)

    def get_request_area(
        self, area_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/request-areas/{area_id}", None, headers)

    def list_request_areas(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/request-areas", params, headers)

    def lock_request_area(
        self, area_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/request-areas/{area_id}/lock", payload or {}, headers
        )

    # ── Video requests ─────────────────────────────────────────────────────

    def create_video_request(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/video-requests", payload, headers)

    def get_video_request(
        self, request_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/video-requests/{request_id}", None, headers
        )

    def list_video_requests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/video-requests", params, headers)

    def log_justification(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/video-requests/{request_id}/justification", payload, headers
        )

    def submit_video_request(
        self,
        request_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/video-requests/{request_id}/submit", payload or {}, headers
        )

    def withdraw_video_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/video-requests/{request_id}/withdraw", payload, headers
        )

    def review_audit(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/video-requests/{request_id}/audit-review", payload, headers
        )

    # ── Consent solicitations ──────────────────────────────────────────────

    def get_solicitation(
        self, solicitation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/consent-solicitations/{solicitation_id}", None, headers
        )

    def list_solicitations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/consent-solicitations", params, headers)

    def share_footage(
        self, solicitation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/consent-solicitations/{solicitation_id}/share",
            payload,
            headers,
        )

    def decline_solicitation(
        self, solicitation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/consent-solicitations/{solicitation_id}/decline",
            payload,
            headers,
        )

    # ── Shared clips ───────────────────────────────────────────────────────

    def get_shared_clip(self, clip_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/shared-clips/{clip_id}", None, headers)

    def list_shared_clips(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/shared-clips", params, headers)

    def purge_clip(
        self, clip_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/shared-clips/{clip_id}/purge", payload, headers
        )

    # ── Resident posts ─────────────────────────────────────────────────────

    def create_post(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/resident-posts", payload, headers)

    def get_post(self, post_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/resident-posts/{post_id}", None, headers)

    def list_posts(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/resident-posts", params, headers)

    def flag_post(
        self, post_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/resident-posts/{post_id}/flag", payload, headers
        )

    def revise_post(
        self, post_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/resident-posts/{post_id}/revise", payload, headers
        )

    # ── Moderation cases ───────────────────────────────────────────────────

    def open_moderation_case(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/moderation-cases", payload, headers)

    def get_moderation_case(
        self, case_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/moderation-cases/{case_id}", None, headers
        )

    def list_moderation_cases(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/moderation-cases", params, headers)

    def decide_moderation_case(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/moderation-cases/{case_id}/decide", payload, headers
        )

    # ── Transparency reports ───────────────────────────────────────────────

    def compile_report(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/transparency-reports", payload, headers)

    def get_report(self, report_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/transparency-reports/{report_id}", None, headers
        )

    def list_reports(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/transparency-reports", params, headers)

    def certify_report(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/transparency-reports/{report_id}/certify", payload, headers
        )

    # ── Retention sweeps ───────────────────────────────────────────────────

    def run_retention_sweep(
        self, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/retention-sweeps", payload or {}, headers
        )
