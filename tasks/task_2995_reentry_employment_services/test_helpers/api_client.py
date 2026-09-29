"""
Endpoint client for the Reentry Employment Services API.

One method per endpoint in the PRD's endpoint table. Every method returns the
raw requests.Response so that tests can assert HTTP status codes and then hand
the response to validate_success / validate_error.

This module also owns instant canonicalisation. The PRD declares timestamps as
ISO 8601 UTC instants with three fractional digits, but a conformant server may
serialise an equivalent instant with a different sub-second width or a "+00:00"
offset instead of "Z". canonical_instant() reduces any such spelling to a
single canonical form so equality comparisons in tests compare instants and not
string formatting.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

_OFFSET_SUFFIX_RE = re.compile(r"([+-])(\d{2}):?(\d{2})$")
_FRACTION_RE = re.compile(r"\.(\d+)$")


def canonical_instant(value: Any) -> Any:
    """
    Reduce an ISO 8601 UTC instant to the canonical spelling
    YYYY-MM-DDTHH:MM:SS.mmmZ.

    Non-string values and strings that do not look like instants (calendar
    dates, for example) are returned untouched, so this is safe to apply to any
    field value.
    """
    if not isinstance(value, str) or "T" not in value:
        return value

    text = value.strip()

    # Normalise the zone designator to UTC.
    if text.endswith("Z") or text.endswith("z"):
        body = text[:-1]
    else:
        match = _OFFSET_SUFFIX_RE.search(text)
        if match is None:
            return value
        if match.group(1) != "+" or match.group(2) != "00" or match.group(3) != "00":
            # A non-UTC offset is a different spelling than the PRD declares;
            # leave it alone so the assertion reports the real difference.
            return value
        body = text[: match.start()]

    # Normalise the fractional-second width to exactly three digits.
    fraction = _FRACTION_RE.search(body)
    if fraction is None:
        return f"{body}.000Z"
    digits = fraction.group(1)
    digits = (digits + "000")[:3]
    return f"{body[: fraction.start()]}.{digits}Z"


def canonical_instants(value: Any) -> Any:
    """Recursively canonicalise every instant-looking string in a structure."""
    if isinstance(value, dict):
        return {k: canonical_instants(v) for k, v in value.items()}
    if isinstance(value, list):
        return [canonical_instants(v) for v in value]
    return canonical_instant(value)


class ApiClient(GenericApiClient):
    """One method per endpoint of the Reentry Employment Services API."""

    # -- Logical clock ------------------------------------------------------

    def set_clock(self, current_utc: str, headers: Optional[Dict[str, str]] = None):
        """POST /_clock/set_current_utc — auth-exempt per the PRD."""
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers or {"Content-Type": "application/json"},
        )

    # -- Participants -------------------------------------------------------

    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", None, headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/participants", None, headers, params)

    def update_participant(self, participant_id, payload, headers):
        return self._request("PUT", f"/participants/{participant_id}", payload, headers)

    def record_assessment(self, participant_id, payload, headers):
        return self._request(
            "POST", f"/participants/{participant_id}/assessment", payload, headers
        )

    def verify_document(self, participant_id, payload, headers):
        return self._request(
            "POST",
            f"/participants/{participant_id}/document-verifications",
            payload,
            headers,
        )

    def put_release_plan(self, participant_id, payload, headers):
        return self._request(
            "PUT", f"/participants/{participant_id}/release-plan", payload, headers
        )

    def approve_release_plan(self, participant_id, headers, payload=None):
        return self._request(
            "POST",
            f"/participants/{participant_id}/release-plan/approve",
            payload if payload is not None else {},
            headers,
        )

    def record_release(self, participant_id, payload, headers):
        return self._request(
            "POST", f"/participants/{participant_id}/release", payload, headers
        )

    def set_suspension(self, participant_id, payload, headers):
        return self._request(
            "POST", f"/participants/{participant_id}/suspension", payload, headers
        )

    def drive_license_relief(self, participant_id, payload, headers):
        return self._request(
            "POST", f"/participants/{participant_id}/license-relief", payload, headers
        )

    def exit_participant(self, participant_id, payload, headers):
        return self._request(
            "POST", f"/participants/{participant_id}/exit", payload, headers
        )

    def get_readiness_summary(self, participant_id, headers):
        return self._request(
            "GET", f"/participants/{participant_id}/readiness-summary", None, headers
        )

    # -- Supervision cases --------------------------------------------------

    def create_supervision_case(self, payload, headers):
        return self._request("POST", "/supervision-cases", payload, headers)

    def get_supervision_case(self, case_id, headers):
        return self._request("GET", f"/supervision-cases/{case_id}", None, headers)

    def list_supervision_cases(self, headers, params=None):
        return self._request("GET", "/supervision-cases", None, headers, params)

    def set_supervision_case_status(self, case_id, payload, headers):
        return self._request(
            "POST", f"/supervision-cases/{case_id}/status", payload, headers
        )

    def decide_work_authorization(self, case_id, payload, headers):
        return self._request(
            "POST", f"/supervision-cases/{case_id}/work-authorization", payload, headers
        )

    # -- Employer partnerships ---------------------------------------------

    def create_partnership(self, payload, headers):
        return self._request("POST", "/employer-partnerships", payload, headers)

    def get_partnership(self, partnership_id, headers):
        return self._request(
            "GET", f"/employer-partnerships/{partnership_id}", None, headers
        )

    def list_partnerships(self, headers, params=None):
        return self._request("GET", "/employer-partnerships", None, headers, params)

    def set_partnership_status(self, partnership_id, payload, headers):
        return self._request(
            "POST", f"/employer-partnerships/{partnership_id}/status", payload, headers
        )

    def record_bonding_agreement(self, partnership_id, payload, headers):
        return self._request(
            "POST",
            f"/employer-partnerships/{partnership_id}/bonding-agreement",
            payload,
            headers,
        )

    def list_partnership_job_openings(self, partnership_id, headers, params=None):
        return self._request(
            "GET",
            f"/employer-partnerships/{partnership_id}/job-openings",
            None,
            headers,
            params,
        )

    # -- Job openings -------------------------------------------------------

    def create_job_opening(self, payload, headers):
        return self._request("POST", "/job-openings", payload, headers)

    def get_job_opening(self, opening_id, headers):
        return self._request("GET", f"/job-openings/{opening_id}", None, headers)

    def list_job_openings(self, headers, params=None):
        return self._request("GET", "/job-openings", None, headers, params)

    def get_match_preview(self, opening_id, headers, params=None):
        return self._request(
            "GET", f"/job-openings/{opening_id}/match-preview", None, headers, params
        )

    # -- Grants -------------------------------------------------------------

    def create_grant(self, payload, headers):
        return self._request("POST", "/grants", payload, headers)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/grants/{grant_id}", None, headers)

    def list_grants(self, headers, params=None):
        return self._request("GET", "/grants", None, headers, params)

    def get_grant_ledger(self, grant_id, headers):
        return self._request("GET", f"/grants/{grant_id}/ledger", None, headers)

    def get_outcome_report(self, grant_id, headers, params=None):
        return self._request(
            "GET", f"/grants/{grant_id}/outcome-report", None, headers, params
        )

    # -- Placements ---------------------------------------------------------

    def create_placement(self, payload, headers):
        return self._request("POST", "/placements", payload, headers)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/placements/{placement_id}", None, headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", "/placements", None, headers, params)

    def respond_to_offer(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/placements/{placement_id}/offer-response", payload, headers
        )

    def separate_placement(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/placements/{placement_id}/separate", payload, headers
        )

    def drive_placement_bonding(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/placements/{placement_id}/bonding", payload, headers
        )

    def record_retention_check(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/placements/{placement_id}/retention-check", payload, headers
        )

    def create_work_shift(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/placements/{placement_id}/work-shifts", payload, headers
        )

    def list_placement_work_shifts(self, placement_id, headers, params=None):
        return self._request(
            "GET", f"/placements/{placement_id}/work-shifts", None, headers, params
        )

    # -- Work shifts --------------------------------------------------------

    def get_work_shift(self, shift_id, headers):
        return self._request("GET", f"/work-shifts/{shift_id}", None, headers)

    def list_work_shifts(self, headers, params=None):
        return self._request("GET", "/work-shifts", None, headers, params)

    def set_work_shift_status(self, shift_id, payload, headers):
        return self._request(
            "POST", f"/work-shifts/{shift_id}/status", payload, headers
        )

    # -- Support requests ---------------------------------------------------

    def create_support_request(self, payload, headers):
        return self._request("POST", "/support-requests", payload, headers)

    def get_support_request(self, request_id, headers):
        return self._request("GET", f"/support-requests/{request_id}", None, headers)

    def list_support_requests(self, headers, params=None):
        return self._request("GET", "/support-requests", None, headers, params)

    def review_support_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/support-requests/{request_id}/review", payload, headers
        )

    def resubmit_support_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/support-requests/{request_id}/resubmit", payload, headers
        )

    def settle_support_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/support-requests/{request_id}/settle", payload, headers
        )

    # -- Readiness sessions and enrollments --------------------------------

    def create_readiness_session(self, payload, headers):
        return self._request("POST", "/readiness-sessions", payload, headers)

    def get_readiness_session(self, session_id, headers):
        return self._request("GET", f"/readiness-sessions/{session_id}", None, headers)

    def list_readiness_sessions(self, headers, params=None):
        return self._request("GET", "/readiness-sessions", None, headers, params)

    def set_session_status(self, session_id, payload, headers):
        return self._request(
            "POST", f"/readiness-sessions/{session_id}/status", payload, headers
        )

    def create_enrollment(self, session_id, payload, headers):
        return self._request(
            "POST", f"/readiness-sessions/{session_id}/enrollments", payload, headers
        )

    def list_session_enrollments(self, session_id, headers, params=None):
        return self._request(
            "GET",
            f"/readiness-sessions/{session_id}/enrollments",
            None,
            headers,
            params,
        )

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", None, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", None, headers, params)

    def set_enrollment_status(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/status", payload, headers
        )
